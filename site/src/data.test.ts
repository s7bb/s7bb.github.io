import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  last7DaysByDayBothDirections,
  terminusLabelLong,
  terminusLabelShort,
  terminusAggregate,
  num,
  germanMonth,
} from "./data.js";
import type { S7Data, Arrival } from "./data.js";

function arrival(overrides: Partial<Arrival>): Arrival {
  return {
    train_id: "x",
    line: "S7",
    station: "Baierbrunn",
    direction: "",
    direction_bucket: "muenchen",
    scheduled_time: "2026-05-01T08:00:00",
    actual_time: null,
    delay_minutes: 0,
    cancelled: false,
    reason: null,
    train_number: null,
    ...overrides,
  };
}

function fixture(arrivals: Arrival[]): S7Data {
  return {
    generated_at: "2026-05-08T07:00:00Z",
    station: "Baierbrunn",
    line: "S7",
    window_days: 7,
    arrivals,
    aggregates: {
      today:        { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
      last_7_days:  { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0,
        by_direction: {
          muenchen:       { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
          wolfratshausen: { total: 0, on_time: 0, late: 0, cancelled: 0, avg_delay_min: 0, missing: 0 },
        }},
    },
    expected_slots: { today: { muenchen: [], wolfratshausen: [] } },
  };
}

describe("last7DaysByDayBothDirections", () => {
  it("returns empty array when no arrivals", () => {
    expect(last7DaysByDayBothDirections(fixture([]))).toEqual([]);
  });

  it("groups by date and direction, computing scheduled / cancelled / avg_delay", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", delay_minutes: 4, cancelled: false }),
      arrival({ scheduled_time: "2026-05-01T10:00:00", direction_bucket: "muenchen", delay_minutes: null, cancelled: true }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "wolfratshausen", delay_minutes: 1, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows).toHaveLength(1);
    expect(rows[0].date).toBe("2026-05-01");
    expect(rows[0].muenchen).toEqual({ avg_delay: 3, cancelled: 1, scheduled: 3 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 1, cancelled: 0, scheduled: 1 });
  });

  it("ignores arrivals with direction_bucket 'unknown'", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "unknown", delay_minutes: 99, cancelled: false }),
    ]);
    expect(last7DaysByDayBothDirections(data)).toEqual([]);
  });

  it("yields zero sub-row when one direction is absent on a date", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 5, cancelled: false }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows[0].muenchen).toEqual({ avg_delay: 5, cancelled: 0, scheduled: 1 });
    expect(rows[0].wolfratshausen).toEqual({ avg_delay: 0, cancelled: 0, scheduled: 0 });
  });

  it("returns dates ascending across multiple days", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-03T08:00:00", direction_bucket: "muenchen", delay_minutes: 1 }),
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", delay_minutes: 2 }),
      arrival({ scheduled_time: "2026-05-02T08:00:00", direction_bucket: "muenchen", delay_minutes: 3 }),
    ]);
    const rows = last7DaysByDayBothDirections(data);
    expect(rows.map(r => r.date)).toEqual(["2026-05-01", "2026-05-02", "2026-05-03"]);
  });

  it("treats avg_delay as 0 when direction has only cancelled arrivals", () => {
    const data = fixture([
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", cancelled: true, delay_minutes: null }),
    ]);
    expect(last7DaysByDayBothDirections(data)[0].muenchen).toEqual({ avg_delay: 0, cancelled: 1, scheduled: 1 });
  });
});

describe("terminusLabelLong", () => {
  it("returns 'München Hbf' for muenchen", () => {
    expect(terminusLabelLong("muenchen")).toBe("München Hbf");
  });
  it("returns 'Wolfratshausen' for wolfratshausen", () => {
    expect(terminusLabelLong("wolfratshausen")).toBe("Wolfratshausen");
  });
});

describe("terminusLabelShort", () => {
  it("returns 'München' for muenchen", () => {
    expect(terminusLabelShort("muenchen")).toBe("München");
  });
  it("returns 'Wolfratshausen' for wolfratshausen", () => {
    expect(terminusLabelShort("wolfratshausen")).toBe("Wolfratshausen");
  });
});

describe("terminusAggregate", () => {
  // Tests use VITE_DEV_NOW-free `arrival` factory; aggregator filters by
  // Berlin "today" - fix system clock via vi.setSystemTime so dates compare.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts arrived, short_turn, missed (=cancelled), pending per bucket", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "short_turn", terminus_short_turn_station: "München-Solln" }),
      arrival({ scheduled_time: "2026-05-01T09:30:00", direction_bucket: "muenchen", terminus_status: "cancelled" }),
      arrival({ scheduled_time: "2026-05-01T10:00:00", direction_bucket: "muenchen", terminus_status: "pending" }),
    ];
    const agg = terminusAggregate(arrivals, "muenchen");
    expect(agg).toEqual({ arrived: 2, short_turn: 1, missed: 1, pending: 1 });
  });

  it("excludes Baierbrunn-cancelled rows entirely", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", cancelled: true, terminus_status: "cancelled" }),
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });

  it("excludes rows with null/undefined terminus_status", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: null }),
      arrival({ scheduled_time: "2026-05-01T08:30:00", direction_bucket: "muenchen" }), // undefined
      arrival({ scheduled_time: "2026-05-01T09:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });

  it("filters by Berlin 'today' date and by direction_bucket", () => {
    const arrivals = [
      arrival({ scheduled_time: "2026-04-30T20:00:00Z", direction_bucket: "muenchen", terminus_status: "arrived" }), // not today (April 30 in Berlin)
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "muenchen", terminus_status: "arrived" }),
      arrival({ scheduled_time: "2026-05-01T08:00:00", direction_bucket: "wolfratshausen", terminus_status: "arrived" }),
    ];
    expect(terminusAggregate(arrivals, "muenchen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
    expect(terminusAggregate(arrivals, "wolfratshausen")).toEqual({ arrived: 1, short_turn: 0, missed: 0, pending: 0 });
  });
});

describe("num", () => {
  it("passes finite numbers through unchanged, including negatives and floats", () => {
    expect(num(5)).toBe(5);
    expect(num(-3)).toBe(-3);
    expect(num(1.2)).toBe(1.2);
    expect(num(0)).toBe(0);
  });

  it("coerces numeric strings", () => {
    expect(num("7")).toBe(7);
  });

  it("returns 0 for injection payloads, NaN, Infinity, null, undefined, objects", () => {
    expect(num('<img src=x onerror=alert(1)>')).toBe(0);
    expect(num(NaN)).toBe(0);
    expect(num(Infinity)).toBe(0);
    expect(num(null)).toBe(0);
    expect(num(undefined)).toBe(0);
    expect(num({})).toBe(0);
  });
});

describe("germanMonth", () => {
  it("formats a valid period", () => {
    expect(germanMonth("2026-04")).toBe("April 2026");
    expect(germanMonth("2026-01")).toBe("Januar 2026");
    expect(germanMonth("2026-12")).toBe("Dezember 2026");
  });

  it("returns the input unchanged for out-of-range months", () => {
    expect(germanMonth("2026-00")).toBe("2026-00");
    expect(germanMonth("2026-13")).toBe("2026-13");
  });

  it("returns the input unchanged for non-period strings (incl. payloads)", () => {
    expect(germanMonth("<img src=x onerror=alert(1)>")).toBe("<img src=x onerror=alert(1)>");
    expect(germanMonth("2026-4")).toBe("2026-4");
    expect(germanMonth("")).toBe("");
  });
});
