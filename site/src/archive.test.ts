import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadIndex, loadMonth, _resetCache } from "./archive.js";
import { _primeDataBase } from "./config.js";

const indexJson = {
  generated_at: "2026-05-07T07:00:00+00:00",
  station: "Baierbrunn",
  months: [
    {
      period: "2026-04", finalized: true,
      total: 1234, on_time: 1100, late: 120, cancelled: 14, avg_delay_min: 1.2,
      by_direction: {
        muenchen:       { total: 617, on_time: 550, late: 60, cancelled: 7, avg_delay_min: 1.3 },
        wolfratshausen: { total: 617, on_time: 550, late: 60, cancelled: 7, avg_delay_min: 1.1 },
      },
    },
  ],
};

const monthJson = {
  generated_at: "2026-04-30T23:59:00+00:00",
  station: "Baierbrunn", line: "S7", period: "2026-04", finalized: true,
  arrivals: [],
  aggregates: { total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0,
    by_direction: { muenchen: {}, wolfratshausen: {} } },
  daily: [{ date: "2026-04-01", total: 1, on_time: 1, late: 0, cancelled: 0, avg_delay_min: 0 }],
  daily_by_direction: { muenchen: [], wolfratshausen: [] },
};

beforeEach(() => {
  _resetCache();
  _primeDataBase("../data");
  vi.restoreAllMocks();
});

describe("loadIndex", () => {
  it("fetches and parses index.json", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(indexJson), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months[0].period).toBe("2026-04");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("caches across calls within a session", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(indexJson), { status: 200 }) as Response),
    );
    await loadIndex();
    await loadIndex();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("throws on non-200", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("nope", { status: 404 }) as Response,
    );
    await expect(loadIndex()).rejects.toThrow();
  });

  it("drops months whose period is not a valid YYYY-MM string", async () => {
    const hostile = {
      ...indexJson,
      months: [
        ...indexJson.months,
        { ...indexJson.months[0], period: '"><img src=x onerror=alert(1)>' },
        { ...indexJson.months[0], period: 42 },
        { ...indexJson.months[0], period: "2026-4" },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(hostile), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months).toHaveLength(1);
    expect(idx.months[0].period).toBe("2026-04");
  });

  it("tolerates a missing months array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ generated_at: "x", station: "Baierbrunn" }), { status: 200 }) as Response,
    );
    const idx = await loadIndex();
    expect(idx.months).toEqual([]);
  });
});

describe("loadMonth", () => {
  it("fetches archive/YYYY-MM.json", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(monthJson), { status: 200 }) as Response,
    );
    const m = await loadMonth("2026-04");
    expect(m.period).toBe("2026-04");
    expect(fetchSpy.mock.calls[0][0]).toContain("2026-04.json");
  });

  it("caches per-month", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(monthJson), { status: 200 }) as Response),
    );
    await loadMonth("2026-04");
    await loadMonth("2026-04");
    await loadMonth("2026-05");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("rejects malformed period", async () => {
    await expect(loadMonth("2026-4")).rejects.toThrow();
    await expect(loadMonth("../etc")).rejects.toThrow();
  });
});
